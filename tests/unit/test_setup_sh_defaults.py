"""Padrões de progress e prefetch no setup.sh: ligados, e só "false" (maiúsculas ou minúsculas) desliga.

Executa no bash os trechos reais do setup.sh que definem os padrões, leem os argumentos chave=valor e normalizam os
dois valores (prefetch vai para o extra-vars como JSON, então só pode sair true ou false).
"""
import os
import re
import subprocess
import unittest

from _loader import REPO


def trechos_do_setup():
    with open(os.path.join(REPO, "setup.sh")) as f:
        s = f.read()
    padroes = re.findall(r"^(?:progress|prefetch)=\w+;$", s, re.M)
    argumentos = re.search(r'^for ARGUMENT in "\$@"\n.*?^done$', s, re.M | re.S).group(0)
    normalizacao = re.search(r"^# progress e prefetch só desligam.*?(?=^\n)", s, re.M | re.S).group(0)
    return "\n".join(padroes + [argumentos, normalizacao, 'echo "$progress $prefetch"'])


class SetupShDefaultsTest(unittest.TestCase):
    def valores(self, *args):
        p = subprocess.run(["bash", "-c", trechos_do_setup(), "setup.sh", *args], capture_output=True, text=True,
                           env={"PATH": os.environ["PATH"]}, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.split()

    def test_ligados_por_padrao(self):
        self.assertEqual(self.valores(), ["true", "true"])
        self.assertEqual(self.valores("progress=", "prefetch="), ["true", "true"])
        self.assertEqual(self.valores("progress=true", "prefetch=true"), ["true", "true"])

    def test_false_desliga_cada_um(self):
        self.assertEqual(self.valores("progress=false"), ["false", "true"])
        self.assertEqual(self.valores("prefetch=false"), ["true", "false"])
        self.assertEqual(self.valores("progress=FALSE", "prefetch=False"), ["false", "false"])

    def test_valor_desconhecido_mantem_o_padrao(self):
        self.assertEqual(self.valores("progress=sim", "prefetch=1"), ["true", "true"])


if __name__ == "__main__":
    unittest.main()
