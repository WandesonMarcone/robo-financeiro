"""Entrega auditável de atualização diária para ETFs e BDRs favoritados."""
from __future__ import annotations

from datetime import date
import logging

from pipeline_dados.repositorio_favoritos_internacionais import RepositorioFavoritosInternacionais
from services.historico_operacional import registrar_notificacao

logger = logging.getLogger(__name__)


def _destino(usuario):
    return usuario.get("telegram_chat_id") or usuario.get("telegram_user_id")


def _ja_enviada(usuario_id, ticker, tipo, referencia):
    """Evita duplicar uma atualização diária já entregue com sucesso."""
    from atualizador_documentos import SessionDB
    from sqlalchemy import text
    sessao = SessionDB()
    try:
        retorno = sessao.execute(text("""
            SELECT 1 FROM historico_notificacoes
            WHERE usuario_id=:usuario_id AND ticker=:ticker AND tipo=:tipo
              AND status='ENVIADA' AND enviado_em::date=:referencia
            LIMIT 1
        """), {"usuario_id": usuario_id, "ticker": ticker,
               "tipo": f"ATUALIZACAO_DIARIA_{tipo}", "referencia": referencia}).first()
        return retorno is not None
    except Exception:
        logger.warning("Não foi possível checar deduplicação de notificação", exc_info=True)
        return False
    finally:
        sessao.close()


def _mensagem(item):
    ticker, tipo = item["ticker"], item["tipo"]
    preco = item.get("preco")
    variacao = item.get("variacao")
    linhas = [f"{'🌐' if tipo == 'ETF' else '🌍'} *Atualização diária — {tipo}*", "", f"*{ticker}*"]
    linhas.append(f"Fechamento: R$ {float(preco):,.2f}" if preco is not None else "Fechamento: não informado")
    if variacao is not None:
        linhas.append(f"Variação do pregão: {float(variacao):+.2f}%")
    linhas += [f"Referência: {item.get('referencia') or 'não informada'}", "Fonte: Yahoo Finance (complementar)"]
    return "\n".join(linhas)


def notificar_atualizacoes_diarias(resultados, tipo=None, repo=None, enviar=None):
    """Envia apenas a seguidores do mesmo instrumento e grava cada tentativa.

    Não cria alerta de mercado nem usa zero como preço. A preferência individual
    ``alertas_ativos`` é obrigatória para entrega.
    """
    repo = repo or RepositorioFavoritosInternacionais()
    if enviar is None:
        from bot.loader import bot
        enviar = lambda destino, texto: bot.send_message(destino, texto, parse_mode="Markdown")
    resumo = {"enviadas": 0, "falhas": 0, "sem_seguidores": 0, "ignoradas": 0}
    for item in resultados or []:
        if not isinstance(item, dict) or item.get("tipo") not in {"ETF", "BDR"}:
            continue
        if tipo and item["tipo"] != str(tipo).upper():
            continue
        if item.get("preco") is None:
            resumo["ignoradas"] += 1
            continue
        referencia = str(item.get("referencia") or date.today().isoformat())[:10]
        seguidores = repo.usuarios_que_acompanham(item["ticker"], item["tipo"])
        if not seguidores:
            resumo["sem_seguidores"] += 1
            continue
        texto = _mensagem(item)
        for usuario in seguidores:
            destino = _destino(usuario)
            if not destino or _ja_enviada(usuario["id"], item["ticker"], item["tipo"], referencia):
                resumo["ignoradas"] += 1
                continue
            try:
                enviar(destino, texto)
                registrar_notificacao(
                    f"ATUALIZACAO_DIARIA_{item['tipo']}", ticker=item["ticker"],
                    destinatario=destino, resumo=texto, enviada=True,
                    audiencia="USUARIO", usuario_id=usuario["id"],
                )
                resumo["enviadas"] += 1
            except Exception as exc:
                logger.warning("Falha ao entregar %s a usuário %s", item["ticker"], usuario["id"], exc_info=True)
                registrar_notificacao(
                    f"ATUALIZACAO_DIARIA_{item['tipo']}", ticker=item["ticker"],
                    destinatario=destino, resumo=texto, enviada=False, erro=type(exc).__name__,
                    audiencia="USUARIO", usuario_id=usuario["id"],
                )
                resumo["falhas"] += 1
    return resumo


def notificar_resumo_admin(resultado, tipo, enviar=None):
    """Entrega operacional separada ao administrador, auditada como tal."""
    import config
    destino = str(getattr(config, "TELEGRAM_ADMIN_ID", "") or "").strip()
    if not destino:
        return False
    classe = str(tipo or resultado.get("tipo") or "instrumentos").upper()
    texto = (
        f"📋 *Ciclo diário — {classe}*\n\n"
        f"Processados: {resultado.get('processados', 0)}\n"
        f"Falhas de coleta: {len(resultado.get('falhas') or [])}\n"
        f"Entregas a favoritos: {(resultado.get('notificacoes') or {}).get('enviadas', 0)}\n"
        f"Falhas de entrega: {(resultado.get('notificacoes') or {}).get('falhas', 0)}"
    )
    try:
        if enviar is None:
            from bot.loader import bot
            enviar = lambda chat, msg: bot.send_message(chat, msg, parse_mode="Markdown")
        enviar(destino, texto)
        registrar_notificacao(f"RESUMO_CICLO_{classe}", destinatario=destino,
                               resumo=texto, enviada=True, audiencia="ADMINISTRADOR")
        return True
    except Exception as exc:
        registrar_notificacao(f"RESUMO_CICLO_{classe}", destinatario=destino,
                               resumo=texto, enviada=False, erro=type(exc).__name__,
                               audiencia="ADMINISTRADOR")
        return False
