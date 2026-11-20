"""Pruebas de la instalación con reintentos (robot/instalar.sh) y de su aviso de fallo temporal."""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from permisos import aviso_fallo_instalacion  # noqa: E402

BASH = shutil.which("bash")


class AvisoFalloInstalacion(unittest.TestCase):
    def test_deja_claro_que_no_es_un_rechazo(self):
        for fusionar in (False, True):
            texto = aviso_fallo_instalacion(fusionar)
            self.assertIn("Fallo temporal", texto)
            self.assertIn("no es un rechazo", texto)
            self.assertIn("No hay nada mal en la propuesta", texto)
            self.assertNotIn("❌", texto)
            self.assertNotIn("no puede aceptar", texto)

    def test_dice_en_que_punto_se_quedo(self):
        self.assertIn("todavía no se ha comprobado", aviso_fallo_instalacion(False))
        self.assertIn("ya estaba aceptada", aviso_fallo_instalacion(True))


@unittest.skipUnless(BASH and os.name != "nt", "necesita bash de Linux (se prueba en GitHub)")
class InstalarConReintentos(unittest.TestCase):
    """Sustituye `python` por uno falso que crea un `pip` que falla las primeras N veces."""

    def ejecutar(self, fallos):
        with tempfile.TemporaryDirectory() as carpeta:
            carpeta = pathlib.Path(carpeta)
            falsos = carpeta / "falsos"
            falsos.mkdir()
            (falsos / "python").write_text(
                "#!/usr/bin/env bash\n"
                '[ "$1" = "-m" ] && [ "$2" = "venv" ] || exit 9\n'
                'mkdir -p "$3/bin"\n'
                'cat > "$3/bin/pip" <<FIN\n'
                "#!/usr/bin/env bash\n"
                f'echo "\$*" >> "{carpeta}/llamadas"\n'
                f'n=\$(wc -l < "{carpeta}/llamadas")\n'
                f'[ "\$n" -gt {fallos} ]\n'
                "FIN\n"
                'chmod +x "$3/bin/pip"\n')
            (falsos / "python").chmod(0o755)
            entorno = dict(os.environ, PATH=f"{falsos}:{os.environ['PATH']}", ROBOT_ESPERA_REINTENTO="0")
            salida = subprocess.run([BASH, str(RAIZ / "instalar.sh"), str(carpeta / "venv")],
                                    capture_output=True, text=True, env=entorno)
            llamadas = (carpeta / "llamadas").read_text().splitlines()
            return salida, llamadas

    def test_primer_intento_bien(self):
        salida, llamadas = self.ejecutar(fallos=0)
        self.assertEqual(salida.returncode, 0)
        self.assertEqual(len(llamadas), 1)
        for opcion in ("--retries 5", "--timeout 60", "--require-hashes", "--only-binary :all:", "--no-deps"):
            self.assertIn(opcion, llamadas[0])

    def test_reintenta_tras_un_corte(self):
        salida, llamadas = self.ejecutar(fallos=2)
        self.assertEqual(salida.returncode, 0)
        self.assertEqual(len(llamadas), 3)
        self.assertIn("intento 1 de 3", salida.stdout)
        self.assertNotIn("::error", salida.stdout)

    def test_tres_fallos_avisa_de_fallo_temporal(self):
        salida, llamadas = self.ejecutar(fallos=3)
        self.assertEqual(salida.returncode, 1)
        self.assertEqual(len(llamadas), 3)
        self.assertIn("::error title=Fallo temporal de instalación (no es un rechazo)::", salida.stdout)


if __name__ == "__main__":
    unittest.main()
