from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

# Aponta para o banco de dados que o seu motor de dados alimenta
DB_PATH = "sqlite:///pipeline_dados/banco_institucional.db"

class Ativo(Base):
    __tablename__ = 'ativos'
    id = Column(Integer, primary_key=True)
    ticker = Column(String, unique=True, nullable=False)
    tipo = Column(String)

class DocumentosQualitativos(Base):
    __tablename__ = 'documentos_qualitativos'
    id = Column(Integer, primary_key=True)
    ticker = Column(String, nullable=False)
    tipo_documento = Column(String) 
    data_publicacao = Column(DateTime)
    url_pdf = Column(String)
    resumo_ia = Column(Text)

    status_processamento = Column(String) 

# Configurando a Sessão para o bot interagir com o SQLite
engine = create_engine(DB_PATH)
SessionDB = sessionmaker(bind=engine)