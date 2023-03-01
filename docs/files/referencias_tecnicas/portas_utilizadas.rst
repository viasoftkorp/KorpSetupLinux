Portas Utilizadas
-----------------

Para o devido funcionamento do servidor Linux é necessária a comunicação das devidas portas nos seguintes endereços.

Portas necessárias para a rede externa:

    ======== ============== ================== ================================================================================= ==================
    Porta    Tipo           Objetivo           Endereço                                                                           Máquina
    ======== ============== ================== ================================================================================= ==================
    443      saída          Comunicação https  \*.korp.com.br                                                                     Servidor Windows
    443      saída          Comunicação https  :doc:`Verifique os endereços </files/referencias_tecnicas/enderecos_utilizados>`   Servidor Linux
    4505     saída          SaltStack          144.22.162.228                                                                     Servidor Linux
    4506     saída          SaltStack          144.22.162.228                                                                     Servidor Linux
    10051    saída          Zabbix             144.22.162.228                                                                     Servidor Linux
    ======== ============== ================== ================================================================================= ==================

Portas necessárias para a rede interna:

    ======== ======== ====================== ================ =================
    Porta    Tipo     Objetivo               Endereço         Máquina
    ======== ======== ====================== ================ =================
    1504     entrada  Comunicação Windows    ``rede interna`` Servidor Windows
    1433     entrada  Comunicação SQL Server ``rede interna`` Servidor Windows
    ======== ======== ====================== ================ =================
