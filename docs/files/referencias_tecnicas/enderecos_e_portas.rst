Portas Utilizadas
-----------------

Para o devido funcionamento do servidor Linux é necessária a comunicação das devidas portas nos seguintes endereços.


Portas necessárias para a rede externa:

    ======== ============== ================== ================ ===============
    Porta    Tipo           Objetivo           Endereço         Máquina
    ======== ============== ================== ================ ===============
    80       saída          Comunicação http   \*               Servidor LInux
    443      saída          Comunicação https  \*               Servidor LInux
    4505     saída          SaltStack          144.22.162.228   Servidor LInux
    4506     saída          SaltStack          144.22.162.228   Servidor LInux
    10051    saída          Zabbix             144.22.162.228   Servidor LInux
    ======== ============== ================== ================ ===============


Portas necessárias para a rede interna:

    ======== ======== ====================== ================ =================
    Porta    Tipo     Objetivo               Endereço         Máquina
    ======== ======== ====================== ================ =================
    1504     entrada  Comunicação Windows    ``rede interna`` Servidor Windows
    1433     entrada  Comunicação SQL Server ``rede interna`` Servidor Windows
    ======== ======== ====================== ================ =================
