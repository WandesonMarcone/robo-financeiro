"""Leitura e gravação do histórico de atualizações cíclicas."""
from __future__ import annotations

from pipeline_dados.conexao import obter_session_factory
from pipeline_dados.modelos_execucoes import ExecucaoCiclica


class RepositorioExecucoesCiclicas:
    def registrar(self, **campos):
        """Insere ou atualiza uma execução identificada pelo run do GitHub."""
        fabrica = obter_session_factory()
        with fabrica() as sessao:
            item = (
                sessao.query(ExecucaoCiclica)
                .filter(ExecucaoCiclica.run_id == campos["run_id"])
                .one_or_none()
            )
            if item is None:
                item = ExecucaoCiclica(**campos)
                sessao.add(item)
            else:
                for nome, valor in campos.items():
                    setattr(item, nome, valor)
            sessao.commit()

    def listar_recentes(self, limite=8):
        limite = max(1, min(int(limite), 20))
        fabrica = obter_session_factory()
        with fabrica() as sessao:
            return list(
                sessao.query(ExecucaoCiclica)
                .order_by(ExecucaoCiclica.concluido_em.desc(), ExecucaoCiclica.id.desc())
                .limit(limite)
                .all()
            )
