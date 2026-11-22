"""Pruebas de la instalación con reintentos (robot/instalar.sh) y de su aviso de fallo temporal."""
import os
import pathlib
import re
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
                '[ "$1" = "-I" ] && [ "$2" = "-B" ] && [ "$3" = "-m" ] && [ "$4" = "venv" ] || exit 9\n'
                '[ "$PYTHONDONTWRITEBYTECODE" = "1" ] || exit 8\n'
                f'ls -A > "{carpeta}/donde"\n'
                'mkdir -p "$5/bin"\n'
                'cat > "$5/bin/pip" <<FIN\n'
                "#!/usr/bin/env bash\n"
                f'echo "\$*" >> "{carpeta}/llamadas"\n'
                f'n=\$(wc -l < "{carpeta}/llamadas")\n'
                f'[ "\$n" -gt {fallos} ]\n'
                "FIN\n"
                'chmod +x "$5/bin/pip"\n')
            (falsos / "python").chmod(0o755)
            # Se lanza desde una carpeta con un `venv.py` malicioso, como sería la raíz del `main` descargado.
            checkout = carpeta / "checkout"
            checkout.mkdir()
            (checkout / "venv.py").write_text("raise SystemExit('ejecutado')\n")
            entorno = dict(os.environ, PATH=f"{falsos}:{os.environ['PATH']}", ROBOT_ESPERA_REINTENTO="0")
            salida = subprocess.run([BASH, str(RAIZ / "instalar.sh"), "venv"], cwd=checkout,
                                    capture_output=True, text=True, env=entorno)
            self.assertNotIn(salida.returncode, (8, 9), salida.stderr)
            self.assertEqual("", (carpeta / "donde").read_text().strip())  # se llama desde una carpeta vacía, no desde el checkout
            self.assertTrue((checkout / "venv" / "bin" / "pip").exists())  # la carpeta relativa sigue siendo la del checkout
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


class PythonAislado(unittest.TestCase):
    """`python -m X` pone la carpeta actual (la raíz del `main` descargado) en sys.path: con un `venv.py` o un
    `unittest.py` ahí, se ejecutaría su código con el permiso del robot. Todas las llamadas con `-m` llevan `-I`."""

    ARCHIVOS = ("robot/instalar.sh", ".github/workflows/permisos.yml", ".github/workflows/pruebas-robot.yml")

    def lineas_con_python(self):
        for nombre in self.ARCHIVOS:
            for n, linea in enumerate((RAIZ.parent / nombre).read_text(encoding="utf-8").splitlines(), 1):
                if linea.lstrip().startswith("#"):
                    continue
                for m in re.finditer(r'(?:^|[\s/"\'])(?:python3?|pip3?)"?((?:\s+-[A-Za-z]+)*)\s+(\S+)', linea):
                    yield f"{nombre}:{n}", m.group(0), m.group(1).split(), m.group(2)

    def test_python_no_deja_pyc(self):
        for nombre in (".github/workflows/permisos.yml", ".github/workflows/pruebas-robot.yml"):
            with self.subTest(nombre=nombre):
                self.assertIn("PYTHONDONTWRITEBYTECODE: '1'", (RAIZ.parent / nombre).read_text(encoding="utf-8"))
        self.assertIn("export PYTHONDONTWRITEBYTECODE=1", (RAIZ / "instalar.sh").read_text(encoding="utf-8"))
        for donde, llamada, opciones, siguiente in self.lineas_con_python():
            if "-I" in opciones:  # `-I` ignora PYTHONDONTWRITEBYTECODE
                with self.subTest(donde=donde):
                    self.assertIn("-B", opciones, f"{donde}: {llamada}")

    def test_todo_python_m_lleva_I(self):
        vistas = 0
        for donde, llamada, opciones, siguiente in self.lineas_con_python():
            if "-m" in opciones or siguiente == "-m":
                vistas += 1
                with self.subTest(donde=donde):
                    self.assertIn("-I", opciones, f"{donde}: {llamada}")
        self.assertGreaterEqual(vistas, 2)  # venv y unittest: si no se ven, el patrón está mal

    def test_los_scripts_van_por_su_ruta_en_robot(self):
        for donde, llamada, opciones, siguiente in self.lineas_con_python():
            if "-m" in opciones or siguiente in ("-m", "install"):
                continue
            with self.subTest(donde=donde):
                self.assertTrue(siguiente.startswith(("robot/", '"$RUNNER_TEMP', "-I")), f"{donde}: {llamada}")


if __name__ == "__main__":
    unittest.main()
