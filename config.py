import os

# --- INFRAESTRUTURA DE BANCO DE DADOS ---
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1U8h3Hw2yBOmCbvBskP9zHyVVJf_3OkXtAopcFSebLvs/edit?usp=drivesdk' 
JSON_KEY = 'credenciais.json' 

# --- CONFIGURAÇÕES DE NOTIFICAÇÃO (TELEGRAM) ---
# 🔒 O Token é secreto e puxado direto do cofre do Render.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 
TELEGRAM_CHAT_ID = "8867098987"

# --- CONFIGURAÇÕES DA IA (GROQ) ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# --- CONFIGURAÇÕES DA BASE DE DADOS (GROQ) ---
DATABASE_URL = os.environ.get("DATABASE_URL")

# ==========================================
# PREFERÊNCIAS DO MENU: ⭐ MEUS FAVORITOS
# ==========================================
# Aqui ficam APENAS os ativos que você quer fixos no menu de favoritos 
# para acesso em 1 clique (sem precisar navegar pelas pastas de setores).

FIXAS_FIIS = ["GARE11", "MXRF11", "VISC11", "HGLG11", "XPML11"]
FIXAS_ACOES = ["PETR4", "VALE3", "WEGE3", "ITUB4"]

# ==========================================
# 🗺️ MAPA DE ISCAS MASTER (CATÁLOGO B3)
# ==========================================
# Este dicionário contém os FIIs do mercado. O robô só usará as iscas 
# cujas chaves (Tickers) estiverem presentes na sua planilha Google Sheets.

MAPA_ISCAS_MASTER = {
    # --- OS SEUS FIIS ATUAIS (Mapeados diretamente do seu TXT) ---
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
    "8": "Outros"
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
    # Bancos e Financeiros
    '00.000.000/0001-91': 'BBAS3',  
    '60.872.504/0001-23': 'ITUB4',  
    '60.746.948/0001-12': 'BBDC4',  
    '90.400.888/0001-42': 'SANB11', 
    '09.346.601/0001-25': 'B3SA3',  
    '00.360.305/0001-04': 'BBSE3',  

    # Petróleo, Gás e Mineração
    '33.000.167/0001-01': 'PETR4',  
    '33.592.510/0001-54': 'VALE3',  
    '06.082.980/0001-03': 'PRIO3',  
    '01.838.723/0001-27': 'BRKM5',  
    '02.351.877/0001-52': 'CSNA3',  
    '60.940.145/0001-14': 'GGBR4',  

    # Energia e Utilidades Públicas
    '00.001.180/0001-26': 'ELET3',  
    '84.683.601/0001-74': 'WEGE3',  
    '02.932.971/0001-15': 'EGIE3',  
    '01.206.065/0001-46': 'SBSP3',  
    '06.981.180/0001-16': 'CMIG4',  
    '39.381.153/0001-08': 'CPLE6',  
    '03.256.096/0001-40': 'ENEV3',  

    # Varejo e Consumo
    '47.960.950/0001-21': 'MGLU3',  
    '07.526.557/0001-00': 'ABEV3',  
    '00.001.180/0001-26': 'LREN3',  
    '16.670.085/0001-55': 'RENT3',  
    '06.164.253/0001-87': 'CRFB3',  
    '08.582.208/0001-08': 'NTCO3',  
    '47.508.411/0001-56': 'PCAR3',  
    '33.014.556/0001-96': 'ASAI3',  

    # Carnes e Proteínas
    '02.916.265/0001-60': 'JBSS3',  
    '01.838.723/0001-27': 'BEEF3',  
    '01.017.595/0001-38': 'MRFG3',  

    # Papel, Celulose e Indústria
    '16.404.287/0001-55': 'SUZB3',  
    '89.637.490/0001-45': 'KLBN11', 
    '02.497.801/0001-24': 'EMBR3',  
    '50.282.735/0001-83': 'VIVA3',  

    # Saúde e Educação
    '43.181.368/0001-22': 'RADL3',  
    '60.933.603/0001-78': 'HAPV3',  
    '02.800.026/0001-40': 'YDUQ3',  

    # Telecom e Tecnologia
    '02.558.157/0001-62': 'VIVT3',  
    '02.421.421/0001-11': 'TIMS3',  
    '01.246.689/0001-36': 'TOTS3'   
}
