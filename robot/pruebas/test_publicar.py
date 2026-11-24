"""Trabajo `publicar` (fase B): catálogo regenerado para las ≤0.2.x y la rama `publicado` (`robot/publicar.py`)."""

import copy
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import lector_app  # noqa: E402
import particion  # noqa: E402
import publicar  # noqa: E402
from test_particion import todo_el_modelo  # noqa: E402

MAIN = "a" * 40


def sueltos_de(catalogo=None):
    return particion.partir(copy.deepcopy(catalogo or todo_el_modelo()))


class CatalogoRegenerado(unittest.TestCase):
    def test_si_no_cambia_nada_no_se_regenera(self):
        catalogo = todo_el_modelo()
        self.assertIsNone(publicar.catalogo_regenerado(sueltos_de(catalogo), particion.texto_json(catalogo)))
        # Aunque el de `main` tenga otra versión u otro formato: cuenta lo que dice.
        otro = dict(catalogo, versionCatalogo=77)
        self.assertIsNone(publicar.catalogo_regenerado(sueltos_de(catalogo), json.dumps(otro).encode()))

    def test_un_cambio_sube_la_version_y_lo_lee_la_app(self):
        catalogo = todo_el_modelo()
        archivos = sueltos_de(catalogo)
        juego = json.loads(archivos["juegos/rance-x/juego.json"])
        juego["sinopsis"] = "Nueva"
        archivos["juegos/rance-x/juego.json"] = particion.texto_json(juego)
        datos = publicar.catalogo_regenerado(archivos, particion.texto_json(catalogo))
        nuevo = lector_app.leer(datos)
        self.assertEqual(32, nuevo["versionCatalogo"])
        self.assertEqual("Nueva", next(j for j in nuevo["juegos"] if j["id"] == "rance-x")["sinopsis"])
        self.assertEqual([], lector_app.errores_de_la_app(nuevo))
        self.assertEqual(publicar.permisos.canales.escribir_como_la_app(nuevo).encode(), datos)

    def test_lo_que_no_se_puede_publicar_para(self):
        catalogo = todo_el_modelo()
        for version in (None, "31", -1, lector_app.VERSION_MAXIMA, 2 ** 31, True):
            with self.subTest(version=version):
                with self.assertRaises(publicar.ErrorPublicar):
                    publicar.catalogo_regenerado(sueltos_de(catalogo), json.dumps(dict(catalogo, versionCatalogo=version)).encode())
        for roto in (None, b"{", b"\xff"):
            with self.subTest(main=roto):
                with self.assertRaises(publicar.ErrorPublicar):
                    publicar.catalogo_regenerado(sueltos_de(catalogo), roto)
        archivos = sueltos_de(catalogo)
        del archivos["juegos/rance-x/juego.json"]
        with self.assertRaises(publicar.ErrorPublicar):
            publicar.catalogo_regenerado(archivos, particion.texto_json(catalogo))
        archivos = sueltos_de(catalogo)
        parche = json.loads(archivos["canales/ornizen/parches/rance-x.json"])
        parche["progreso"] = "x"  # la app no lo lee
        archivos["canales/ornizen/parches/rance-x.json"] = particion.texto_json(parche)
        with self.assertRaises(publicar.ErrorPublicar) as error:
            publicar.catalogo_regenerado(archivos, particion.texto_json(catalogo))
        self.assertIn("progreso", str(error.exception))


class IndicePorJuego(unittest.TestCase):
    def test_la_entrada_de_un_juego(self):
        archivos = sueltos_de()
        archivos["canales/otro_canal/parches/rance-x.json"] = particion.texto_json({"esquema": 1, "juego": "rance-x", "estado": "desarrollo"})
        entrada = publicar.indice_por_juego(archivos)["rance-x"]
        self.assertEqual("Rance X", entrada["titulo"])
        self.assertEqual("activo", entrada["estado"])
        self.assertEqual({"canal": "ornizen", "cuenta": None, "fecha": None}, entrada["alta"])
        self.assertEqual(["steam", "dl-jp"], [e["id"] for e in entrada["ediciones"]])
        self.assertEqual("Steam", entrada["ediciones"][0]["tienda"])
        oficial = next(p for p in entrada["parches"] if p["canal"] == "ornizen")
        self.assertEqual((4, 0, 2), (oficial["versiones"], oficial["publicas"], oficial["retiradas"]))
        self.assertEqual({"version": "1.0.0", "fecha": "2026-11-20", "edicion": "steam"}, oficial["ultima"])
        self.assertEqual({"canales": 2, "versiones": 4, "ultima": "2026-11-20"}, entrada["totales"])
        self.assertEqual([{"canal": "ornizen", "como": ["alta", "edicion", "parche"]}, {"canal": "otro_canal", "como": ["parche"]}],
                         entrada["relacionados"])

    def test_lo_ilegible_no_tumba_el_indice(self):
        archivos = sueltos_de()
        archivos["juegos/roto/juego.json"] = b"{"
        archivos["juegos/rance-x/ediciones/steam.json"] = b"[]"
        archivos["canales/ornizen/parches/rance-x.json"] = particion.texto_json(
            {"esquema": 1, "juego": "rance-x", "ediciones": [5, {"id": "steam", "versiones": [None, {"fecha": 3}]}]})
        indice = publicar.indice_por_juego(archivos)
        self.assertNotIn("roto", indice)
        self.assertEqual(["dl-jp"], [e["id"] for e in indice["rance-x"]["ediciones"]])
        self.assertEqual(1, indice["rance-x"]["parches"][0]["versiones"])

    def test_cinco_mil_juegos_en_trozos(self):
        base = todo_el_modelo()["juegos"][0]
        juegos = [dict(copy.deepcopy(base), id=f"juego-{i:05}") for i in range(5000)]
        archivos = sueltos_de({"esquema": 1, "versionCatalogo": 1, "juegos": juegos})
        publicados = publicar.archivos_publicados(archivos, None, MAIN, "2026-11-24T00:00:00Z")
        trozos = [r for r in publicados if r.startswith("programa/juegos/")]
        self.assertEqual(256, len(trozos))
        total = sum(len(json.loads(publicados[r])["juegos"]) for r in trozos)
        self.assertEqual(5000, total)
        self.assertTrue(all(len(d) < publicar.TOPE_ARCHIVO for d in publicados.values()))
        indice = json.loads(publicados["indice.json"])
        for ruta in trozos:
            self.assertEqual("sha256:" + hashlib.sha256(publicados[ruta]).hexdigest(), indice["trozos"][ruta])
        for ruta in trozos:
            for entrada in json.loads(publicados[ruta])["juegos"]:
                self.assertEqual(ruta, f"programa/juegos/{publicar.trozo(entrada['id'])}.json")

    def test_indice_vacio(self):
        publicados = publicar.archivos_publicados({}, None, MAIN, "2026-11-24T00:00:00Z")
        self.assertEqual(["indice.json"], list(publicados))
        self.assertEqual({}, json.loads(publicados["indice.json"])["trozos"])


def g(*argumentos, cwd):
    entorno = dict(os.environ, GIT_AUTHOR_NAME="x", GIT_AUTHOR_EMAIL="x@x", GIT_COMMITTER_NAME="x", GIT_COMMITTER_EMAIL="x@x")
    return subprocess.run(["git", *argumentos], cwd=cwd, check=True, capture_output=True, env=entorno).stdout.decode().strip()


class ApiFalsa:
    """Lo que el trabajo pide a GitHub. Fusionar = subir el commit de la propuesta a `main` del remoto."""

    def __init__(self, remoto):
        self.remoto, self.llamadas, self.propuestas = remoto, [], 0

    def __call__(self, metodo, ruta, datos=None, tolerar=()):
        self.llamadas.append((metodo, ruta, datos))
        if (metodo, ruta) == ("GET", ""):
            return {"owner": {"login": "OrnizStudio"}}
        if metodo == "GET" and ruta.startswith("/pulls?"):
            return []
        if (metodo, ruta) == ("POST", "/pulls"):
            self.propuestas += 1
            return {"number": 100 + self.propuestas}
        if (metodo, ruta) == ("POST", "/check-runs"):
            return {}
        if metodo == "PUT" and ruta.endswith("/merge"):
            subprocess.run(["git", "push", "--quiet", self.remoto, f"{datos['sha']}:refs/heads/main"], check=True,
                           capture_output=True)
            return {"merged": True}
        raise AssertionError(ruta)


class TrabajoEntero(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        raiz = pathlib.Path(self.tmp.name)
        self.remoto, self.local = str(raiz / "remoto.git"), raiz / "local"
        g("init", "-q", "--bare", "-b", "main", self.remoto, cwd=raiz)
        self.antes = os.getcwd()

    def tearDown(self):
        os.chdir(self.antes)
        self.tmp.cleanup()

    def subir_main(self, archivos):
        trabajo = pathlib.Path(self.tmp.name) / "trabajo"
        if not trabajo.exists():
            g("clone", "-q", self.remoto, str(trabajo), cwd=self.tmp.name)
            g("config", "core.autocrlf", "false", cwd=trabajo)
        else:
            g("pull", "-q", "origin", "main", cwd=trabajo)
        for ruta, datos in archivos.items():
            (trabajo / ruta).parent.mkdir(parents=True, exist_ok=True)
            (trabajo / ruta).write_bytes(datos)
        g("add", "-A", cwd=trabajo)
        g("commit", "-qm", "cambio", cwd=trabajo)
        g("push", "-q", "origin", "HEAD:main", cwd=trabajo)

    def correr(self):
        if not self.local.exists():
            g("init", "-q", str(self.local), cwd=self.tmp.name)
        os.chdir(self.local)
        api, avisos = ApiFalsa(self.remoto), []
        base = publicar.regenerar_catalogo(api, self.remoto, dict(os.environ), avisos.append)
        escrito = publicar.escribir_publicado(self.remoto, dict(os.environ), base, avisos.append)
        os.chdir(self.antes)
        return api, avisos, escrito

    def del_remoto(self, rama, ruta):
        return subprocess.run(["git", "--git-dir", self.remoto, "show", f"{rama}:{ruta}"], capture_output=True, check=True).stdout

    def test_migrado_regenera_publica_y_la_segunda_vez_no_hace_nada(self):
        catalogo = todo_el_modelo()
        archivos = sueltos_de(catalogo)
        self.subir_main({**archivos, "catalogo/catalogo.json": particion.texto_json(catalogo)})
        # Sin cambios en lo que dice: no hay propuesta, pero sí la primera rama `publicado`.
        api, avisos, escrito = self.correr()
        self.assertFalse([c for c in api.llamadas if c[0] == "PUT"])
        self.assertTrue(escrito)
        indice = json.loads(self.del_remoto("publicado", "indice.json"))
        self.assertEqual(31, indice["versionCatalogo"])
        padres = subprocess.run(["git", "--git-dir", self.remoto, "rev-list", "--parents", "-n1", "publicado"],
                                capture_output=True, check=True).stdout.decode().split()
        self.assertEqual(1, len(padres))  # un único commit, sin padres
        # Un cambio en los archivos sueltos: propuesta, comprobación en verde, fusión y catálogo con versión 32.
        juego = json.loads(archivos["juegos/rance-x/juego.json"])
        juego["titulo"] = "Rance X (nuevo)"
        self.subir_main({"juegos/rance-x/juego.json": particion.texto_json(juego)})
        api, avisos, escrito = self.correr()
        check = next(c for c in api.llamadas if c[1] == "/check-runs")[2]
        self.assertEqual(("permisos", "success"), (check["name"], check["conclusion"]))
        nuevo = json.loads(self.del_remoto("main", "catalogo/catalogo.json"))
        self.assertEqual(32, nuevo["versionCatalogo"])
        self.assertEqual("Rance X (nuevo)", next(j for j in nuevo["juegos"] if j["id"] == "rance-x")["titulo"])
        self.assertTrue(escrito)
        self.assertEqual(32, json.loads(self.del_remoto("publicado", "indice.json"))["versionCatalogo"])
        trozo = f"programa/juegos/{publicar.trozo('rance-x')}.json"
        self.assertIn("Rance X (nuevo)", self.del_remoto("publicado", trozo).decode())
        # Otra vez sin cambios: nada.
        api, avisos, escrito = self.correr()
        self.assertFalse([c for c in api.llamadas if c[0] in ("PUT", "POST")])
        self.assertFalse(escrito)

    def test_antes_de_la_migracion_solo_el_indice(self):
        catalogo = todo_el_modelo()
        self.subir_main({"catalogo/catalogo.json": particion.texto_json(catalogo)})
        api, avisos, escrito = self.correr()
        self.assertEqual([], api.llamadas)
        self.assertTrue(escrito)
        trozo = f"programa/juegos/{publicar.trozo('rance-x')}.json"
        self.assertIn("rance-x", self.del_remoto("publicado", trozo).decode())

    def test_si_no_se_puede_juntar_no_toca_main(self):
        catalogo = todo_el_modelo()
        archivos = sueltos_de(catalogo)
        self.subir_main({**archivos, "catalogo/catalogo.json": particion.texto_json(catalogo)})
        self.subir_main({"canales/ornizen/parches/fantasma.json": particion.texto_json({"esquema": 1, "juego": "fantasma"})})
        antes = subprocess.run(["git", "--git-dir", self.remoto, "rev-parse", "main"], capture_output=True).stdout
        with self.assertRaises(publicar.ErrorPublicar):
            self.correr()
        os.chdir(self.antes)
        self.assertEqual(antes, subprocess.run(["git", "--git-dir", self.remoto, "rev-parse", "main"], capture_output=True).stdout)


if __name__ == "__main__":
    unittest.main()
