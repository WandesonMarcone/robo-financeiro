import os

# --- INFRAESTRUTURA DE BANCO DE DADOS ---
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 
JSON_KEY = 'credenciais.json' 

# --- CONFIGURAÇÕES ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 
TELEGRAM_CHAT_ID = "8867098987"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") # CONFIG IA(GROQ)
DATABASE_URL = os.environ.get("DATABASE_URL") # CONFIG BASE DE DADOS

# ==========================================
# PREFERÊNCIAS DO MENU: ⭐ MEUS FAVORITOS
# ==========================================

FIXAS_FIIS = ["GARE11", "MXRF11", "VISC11", "HGLG11", "XPML11"]
FIXAS_ACOES = ["PETR4", "VALE3", "WEGE3", "ITUB4"]
# Dicionário de Favoritos que o bot irá consultar
FAVORITOS = {
    "fii": FIXAS_FIIS,
    "acao": FIXAS_ACOES
}

# --- 🚨 REGRAS FIXAS DEFINIDAS AQUI 🚨 ---

FILTROS_FIXOS = {"fii": {"pvp_min": 0.50, "pvp_max": 1.15, "dy_min": 0.08},"acao": {"pl_min": 2.0, "pl_max": 15.0, "pvp_min": 0.50, "pvp_max": 2.50, "dy_min": 0.06, "roe_min": 0.10}}

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

TIPOS_DOC = {
    "0": "Relatorio Gerencial",
    "1": "Fato Relevante",
    "2": "Informe Mensal",
    "3": "Aviso aos Cotistas",
    "4": "Demonstracoes Financeiras",
    "5": "Nova Emissao de Cotas",
    "6": "Assembleia Geral",
    "7": "Rendimentos",
    "8": "Apresentação Trimestral De Resultados"
    "9": "Outros"
}

# ==========================================
# CONFIGURAÇÕES DO COLETOR CVM (AÇÕES)
# ==========================================

# Mapa de padronização de contas contábeis da CVM
MAPA_CONTAS_CVM = {
    '1.01': 'caixa',               
    '2': 'passivo_total',          
    '3.01': 'receita',             
    '3.11': 'lucro_liquido'        
}

# Dicionário Tradutor (CNPJ para Ticker da B3)
MAPA_CNPJ_B3 = {
    # ==========================================
    # 🏦 Bancos, Seguros e Financeiros
    # ==========================================
    '00.000.000/0001-91': 'BBAS3',   # Banco do Brasil
    '60.872.504/0001-23': 'ITUB4',   # Itaú Unibanco
    '60.746.948/0001-12': 'BBDC4',   # Banco Bradesco
    '90.400.888/0001-42': 'SANB11',  # Banco Santander Brasil
    '30.306.294/0001-45': 'BPAC11',  # BTG Pactual (NOVA)
    '09.346.601/0001-25': 'B3SA3',   # B3 S.A. (Bolsa de Valores)
    '17.344.597/0001-94': 'BBSE3',   # BB Seguridade
    '22.180.207/0001-72': 'CXSE3',   # Caixa Seguridade (NOVA)

    # ==========================================
    # 🛢️ Petróleo, Gás e Mineração
    # ==========================================
    '33.000.167/0001-01': 'PETR4',   # Petrobras
    '33.592.510/0001-54': 'VALE3',   # Vale
    '06.082.980/0001-03': 'PRIO3',   # PetroRio (PRIO)
    '42.150.391/0001-70': 'BRKM5',   # Braskem
    '33.042.730/0001-04': 'CSNA3',   # CSN (Siderúrgica Nacional)
    '33.611.500/0001-19': 'GGBR4',   # Gerdau

    # ==========================================
    # ⚡ Energia, Água e Utilidades (Saneamento)
    # ==========================================
    '00.001.180/0001-26': 'ELET3',   # Eletrobras
    '84.683.601/0001-74': 'WEGE3',   # WEG (Motores e Equipamentos)
    '02.932.971/0001-15': 'EGIE3',   # Engie Brasil
    '17.155.730/0001-64': 'CMIG4',   # Cemig
    '76.483.817/0001-20': 'CPLE6',   # Copel
    '11.505.564/0001-91': 'ENEV3',   # Eneva
    '03.220.438/0001-73': 'EQTL3',   # Equatorial Energia (NOVA)
    '07.859.971/0001-30': 'TAEE11',  # Taesa (Transmissão de Energia) (NOVA)
    '43.776.517/0001-80': 'SBSP3',   # Sabesp (Saneamento SP)
    '17.281.106/0001-03': 'CSMG3',   # Copasa (Saneamento MG) (NOVA)
    '76.484.013/0001-45': 'SAPR11',  # Sanepar (Saneamento PR) (NOVA)

    # ==========================================
    # 🛍️ Varejo, Consumo e Bebidas
    # ==========================================
    '47.960.950/0001-21': 'MGLU3',   # Magazine Luiza
    '07.526.557/0001-00': 'ABEV3',   # Ambev
    '92.754.738/0001-62': 'LREN3',   # Lojas Renner
    '16.670.085/0001-55': 'RENT3',   # Localiza (Aluguel de Carros)
    '06.164.253/0001-87': 'CRFB3',   # Carrefour Brasil
    '32.785.497/0001-97': 'NTCO3',   # Natura & Co
    '47.508.411/0001-56': 'PCAR3',   # Grupo Pão de Açúcar (GPA)
    '06.057.223/0001-71': 'ASAI3',   # Assaí Atacadista
    '18.328.118/0001-09': 'PETZ3',   # Petz (Varejo Pet) (NOVA)

    # ==========================================
    # 🥩 Carnes, Proteínas e Agronegócio
    # ==========================================
    '02.916.265/0001-60': 'JBSS3',   # JBS
    '43.339.004/0001-42': 'BEEF3',   # Minerva Foods
    '01.017.595/0001-38': 'MRFG3',   # Marfrig
    '89.113.800/0001-28': 'SLCE3',   # SLC Agrícola (NOVA)
    '33.453.598/0001-23': 'RAIZ4',   # Raízen (Açúcar, Álcool e Combustíveis) (NOVA)

    # ==========================================
    # 🏗️ Construção Civil e Shopping Centers
    # ==========================================
    '73.178.600/0001-18': 'CYRE3',   # Cyrela (NOVA)
    '08.343.492/0001-20': 'MRVE3',   # MRV Engenharia (NOVA)
    '02.356.282/0001-04': 'EZTC3',   # EZTEC (NOVA)
    '07.816.890/0001-53': 'MULT3',   # Multiplan (Shoppings) (NOVA)
    '51.218.147/0001-93': 'IGTI11',  # Iguatemi (Shoppings) (NOVA)
    '31.628.739/0001-04': 'ALOS3',   # Allos / ex-Aliansce Sonae (Shoppings) (NOVA)

    # ==========================================
    # ✈️ Transportes e Logística
    # ==========================================
    '02.846.056/0001-97': 'CCRO3',   # CCR (Concessões Rodoviárias) (NOVA)
    '02.387.241/0001-60': 'RAIL3',   # Rumo Logística (Ferrovias) (NOVA)
    '09.305.994/0001-29': 'AZUL4',   # Azul Linhas Aéreas (NOVA)

    # ==========================================
    # 🏭 Papel, Celulose e Indústria
    # ==========================================
    '16.404.287/0001-55': 'SUZB3',   # Suzano Papel e Celulose
    '89.637.490/0001-45': 'KLBN11',  # Klabin
    '07.689.002/0001-89': 'EMBR3',   # Embraer (Aeronáutica)
    '50.282.735/0001-83': 'VIVA3',   # Vivara (Joalheria/Indústria)

    # ==========================================
    # 🏥 Saúde e Educação
    # ==========================================
    '61.585.865/0001-51': 'RADL3',   # Raia Drogasil (RD Saúde)
    '61.590.030/0001-56': 'HAPV3',   # Hapvida 
    '08.807.432/0001-10': 'YDUQ3',   # Yduqs (Estácio/Educação)
    '60.840.055/0001-31': 'FLRY3',   # Grupo Fleury (Medicina Diagnóstica) (NOVA)
    '06.047.087/0001-39': 'RDOR3',   # Rede D'Or São Luiz (Hospitais) (NOVA)

    # ==========================================
    # 💻 Telecom e Tecnologia
    # ==========================================
    '02.558.157/0001-62': 'VIVT3',   # Telefônica Brasil (Vivo)
    '02.421.421/0001-11': 'TIMS3',   # TIM Brasil
    '53.113.791/0001-22': 'TOTS3'    # Totvs (Softwares)
}
