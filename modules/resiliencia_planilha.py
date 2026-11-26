"""Operações idempotentes contra Google Sheets com tolerância a rede instável."""

import time


def _status_http(erro):
    resposta = getattr(erro, "response", None)
    return getattr(resposta, "status_code", None) or getattr(erro, "code", None)


def _temporario(erro):
    return isinstance(erro, OSError) or _status_http(erro) in {429, 500, 502, 503, 504}


def executar_com_retentativa(operacao, descricao, sleep=time.sleep, tentativas=4):
    """Repete leituras/gravações do Sheets somente em erros transitórios."""
    for tentativa in range(1, tentativas + 1):
        try:
            return operacao()
        except Exception as erro:
            if not _temporario(erro) or tentativa == tentativas:
                raise
            espera = min(60, 2 ** tentativa)
            print(
                f"{descricao}: HTTP {_status_http(erro) or 'rede'} temporário "
                f"(tentativa {tentativa}/{tentativas}); nova tentativa em {espera}s."
            )
            sleep(espera)


def executar_gravacao_com_retentativa(operacao, descricao, sleep=time.sleep, tentativas=4):
    """Repete apenas interrupções de transporte sem duplicar conteúdo.

    ``batch_update`` reaplica os mesmos valores e intervalos; uma nova tentativa
    após desconexão é segura. O erro final é devolvido como ``False`` para que
    o chamador preserve a fila e a auditoria aponte cobertura incompleta.
    """
    for tentativa in range(1, tentativas + 1):
        try:
            operacao()
            return True
        # requests.ConnectionError, usado pelo gspread, herda de OSError.
        except Exception as erro:
            if not _temporario(erro) or tentativa == tentativas:
                print(f"{descricao}: falhou após {tentativas} tentativa(s): {erro}")
                return False
            espera = 2 ** tentativa
            print(
                f"{descricao}: conexão temporariamente interrompida "
                f"(tentativa {tentativa}/{tentativas}); nova tentativa em {espera}s."
            )
            sleep(espera)
