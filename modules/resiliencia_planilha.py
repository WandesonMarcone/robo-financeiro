"""Operações idempotentes contra Google Sheets com tolerância a rede instável."""

import time


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
        except OSError as erro:
            if tentativa == tentativas:
                print(f"{descricao}: falhou após {tentativas} tentativa(s): {erro}")
                return False
            espera = 2 ** tentativa
            print(
                f"{descricao}: conexão temporariamente interrompida "
                f"(tentativa {tentativa}/{tentativas}); nova tentativa em {espera}s."
            )
            sleep(espera)
