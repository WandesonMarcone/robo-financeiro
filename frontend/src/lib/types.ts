export type Usuario = {
  id: number;
  nome: string;
  email: string;
  papel: string;
  plano: string;
  ativo: boolean;
  telegram_vinculado: boolean;
  ultimo_login: string | null;
  criado_em: string | null;
  atualizado_em: string | null;
};

export type LoginPayload = {
  token: string;
  usuario: Usuario;
};

export type AuthStatus =
  | "loading"
  | "authenticated"
  | "unauthenticated"
  | "error";

export type AuthFailure = {
  statusCode: 401 | 403;
  message: string;
};

export type PaginationMeta = {
  total?: number;
  page?: number;
  page_size?: number;
  has_next?: boolean;
  next_page?: number | null;
  retornados?: number;
};

export type CampoSemantico = {
  semantica?: string | null;
  unidade?: string | null;
  escala?: string | null;
  aplicavel?: boolean | null;
};

export type PlanoResumo = {
  plano: string | null;
  entitlements: string[];
  limites: Record<string, number | null>;
};

export type PosicaoCarteira = {
  id: number;
  ativo_id: number;
  ticker: string | null;
  tipo: string | null;
  quantidade: number | null;
  preco_medio: number | null;
  valor_investido: number | null;
  criado_em: string | null;
  atualizado_em: string | null;
};

export type Acompanhamento = {
  id: number;
  ativo_id: number;
  ticker: string | null;
  tipo: string | null;
  criado_em: string | null;
};

export type Notificacao = {
  id: number;
  tipo: string | null;
  titulo: string | null;
  mensagem: string | null;
  ativo_id: number | null;
  ticker: string | null;
  canal: string | null;
  status: string | null;
  dados: Record<string, unknown> | null;
  criado_em: string | null;
  lida_em: string | null;
  tentativas: number | null;
  enviada_em: string | null;
};

export type AlertaEvento = {
  id: number;
  tipo_alerta: string | null;
  tipo_ativo: string | null;
  ativo_id: number | null;
  ticker: string | null;
  indicador: string | null;
  valor_anterior: number | null;
  valor_atual: number | null;
  variacao_percentual: number | null;
  regra: string | null;
  motivo: string | null;
  severidade: string | null;
  recomendacao: string | null;
  origem: string | null;
  data_referencia: string | null;
  data_evento: string | null;
  telegram_enviado: boolean;
};

export type Preferencias = {
  notificacoes_ativas: boolean;
  notificacoes_preco: boolean;
  notificacoes_dividendos: boolean;
  notificacoes_resultados: boolean;
  notificacoes_documentos: boolean;
  notificacoes_alertas: boolean;
  frequencia_notificacoes: string | null;
  telegram_ativo: boolean;
  web_ativo: boolean;
  relatorios_ativos: boolean;
  frequencia_relatorios: string | null;
  mercado_acoes: boolean;
  mercado_fiis: boolean;
  criado_em: string | null;
  atualizado_em: string | null;
};

export type SnapshotMercado = {
  id: number;
  ativo_id: number | null;
  ticker: string | null;
  tipo: string | null;
  data_referencia: string | null;
  data_coleta: string | null;
  data_publicacao: string | null;
  fonte: string | null;
  preco: number | null;
  dy: number | null;
  pvp: number | null;
  vpa: number | null;
  campos?: Record<string, CampoSemantico>;
  [key: string]: unknown;
};

export type Indicador = {
  id: number;
  ativo_id: number;
  ticker: string | null;
  tipo_ativo: string | null;
  indicador: string;
  valor_atual: number | null;
  valor_anterior: number | null;
  variacao_percentual: number | null;
  data_referencia: string | null;
  data_ultima_alteracao: string | null;
  ultima_coleta: string | null;
  origem: string | null;
  semantica: string | null;
  unidade: string | null;
  escala: string | null;
  aplicavel: boolean | null;
};

export type FreshnessCategoria = {
  categoria: string | null;
  status: string | null;
  valor: number | null;
  data_referencia: string | null;
  data_coleta: string | null;
  data_publicacao: string | null;
  fonte: string | null;
};

export type FreshnessEstado = {
  ticker: string | null;
  tipo: string | null;
  categorias: Record<string, FreshnessCategoria | null>;
};
