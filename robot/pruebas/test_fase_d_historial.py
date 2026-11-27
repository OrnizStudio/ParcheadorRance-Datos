"""Fase D9: el Historial global (`historial/central/<AAAA-MM>.json`, docs/canales.md §1 y §2.2).

Al fusionar un juego nuevo, una edición nueva o un cambio en la ficha central de un canal, el robot pone como mensaje
del commit una línea `Historial-central: {…}` (`solicitudes.linea_historial`). El trabajo `publicar` la convierte en
una fila del mes, con los archivos y campos que cambió ese commit en `juegos/<juego>/`, y la deja en `main` en la misma
propuesta que el catálogo.
"""

import json
import os
import pathlib
import re
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import particion  # noqa: E402
import permisos  # noqa: E402
import publicar  # noqa: E402
import solicitudes  # noqa: E402
from test_fase_d_solicitudes_programa import admin, juzgar, main_es  # noqa: E402
from test_particion import todo_el_modelo  # noqa: E402
from test_publicar import ApiFalsa, TrabajoEntero, g, sueltos_de  # noqa: E402
from permisos import Permisos, Rol  # noqa: E402
from test_sueltos import YO, Propuesta  # noqa: E402


def sol(tipo="central", canal="rance_es", juego="rance-x", directa=True):
    return solicitudes.Solicitud(tipo, canal, juego, directa)


class LineaDelHistorial(unittest.TestCase):
    def test_ida_y_vuelta(self):
        linea = solicitudes.linea_historial(sol(), "eva-trad", 7, 42)
        self.assertTrue(linea.startswith("Historial-central: {"))
        self.assertNotIn("\n", linea)
        self.assertEqual({"canal": "rance_es", "cuenta": "eva-trad", "cuentaId": 7, "tipo": "central",
                          "juego": "rance-x", "directa": True, "propuesta": 42}, publicar.fila_de_la_linea(linea))

    def test_vale_la_ultima_y_solo_al_principio_de_linea(self):
        buena = solicitudes.linea_historial(sol(juego="otro"), "eva", 7, 5)
        mala = solicitudes.linea_historial(sol(), "suplanta", 9, 1)
        self.assertEqual("otro", publicar.fila_de_la_linea(f"Título (#5)\n\n{mala}\n{buena}\n")["juego"])
        self.assertIsNone(publicar.fila_de_la_linea(f"texto {buena}"))
        self.assertIsNone(publicar.fila_de_la_linea(""))
        self.assertIsNone(publicar.fila_de_la_linea(None))

    def test_lo_que_no_vale_no_sale(self):
        base = json.loads(solicitudes.linea_historial(sol(), "eva", 7, 42)[len(solicitudes.MARCA_HISTORIAL):])
        malos = [
            {"v": 2}, {"canal": "Rance ES"}, {"canal": "ab"}, {"canal": "x" * 21}, {"juego": "../etc"},
            {"juego": "a" * 65}, {"juego": ""}, {"cuenta": "-eva"}, {"cuenta": "e" * 40}, {"cuenta": "eva<b>"},
            {"cuentaId": "7"}, {"cuentaId": 0}, {"cuentaId": True}, {"cuentaId": 7.0}, {"propuesta": -1},
            {"propuesta": None}, {"tipo": "canal"}, {"tipo": "verificacion"}, {"directa": "si"},
        ]
        for cambio in malos:
            with self.subTest(cambio=cambio):
                texto = solicitudes.MARCA_HISTORIAL + json.dumps({**base, **cambio})
                self.assertIsNone(publicar.fila_de_la_linea(texto))
        self.assertIsNone(publicar.fila_de_la_linea(solicitudes.MARCA_HISTORIAL + "{no es json}"))
        self.assertIsNone(publicar.fila_de_la_linea(solicitudes.MARCA_HISTORIAL + "[1, 2]"))
        # Un nombre con caracteres raros nunca llega: la cuenta y el juego van validados.
        self.assertIsNone(publicar.fila_de_la_linea(solicitudes.MARCA_HISTORIAL + json.dumps({**base, "juego": "ä"})))


class LaLineaEstricta(unittest.TestCase):
    def test_json_estricto(self):
        linea = solicitudes.linea_historial(sol(), "eva", 7, 42)
        self.assertIsNone(publicar.fila_de_la_linea(linea[:-1] + ', "cuenta": "otra"}'))   # clave repetida
        self.assertIsNone(publicar.fila_de_la_linea(linea[:-1] + ', "x": NaN}'))
        self.assertIsNone(publicar.fila_de_la_linea(linea[:-1] + ', "x": ' + "9" * 400 + "}"))

    def test_solo_lineas_de_verdad(self):
        linea = solicitudes.linea_historial(sol(), "eva", 7, 42)
        # Separadores que `splitlines()` sí cortaría: la marca no está al principio de una línea.
        for separador in ("\x1c", "\x0b", "\u2028", "\x85"):
            with self.subTest(separador=repr(separador)):
                self.assertIsNone(publicar.fila_de_la_linea(f"texto{separador}{linea}"))
        self.assertIsNone(publicar.fila_de_la_linea(f"{linea}\x0bbasura"))
        self.assertEqual(42, publicar.fila_de_la_linea(f"Título\r\n\r\n{linea}\r\n")["propuesta"])
        self.assertIsNone(publicar.fila_de_la_linea(linea[:-1] + ', "relleno": "' + "x" * 5000 + '"}'))


class LaFusionDelRobot(unittest.TestCase):
    def test_titulo_y_mensaje_siempre_del_robot(self):
        for titulo in ("Historial-central: {\"v\":1}", "x HISTORIAL-CENTRAL: {}", "a\nHistorial-central: {}", None, ""):
            with self.subTest(titulo=titulo):
                fusion = permisos.datos_de_fusion("c" * 40, 60, titulo, None, "eva", 7)
                self.assertEqual(("c" * 40, "squash"), (fusion["sha"], fusion["merge_method"]))
                self.assertNotIn("historial-central:", (fusion["commit_title"] + fusion["commit_message"]).lower())
                self.assertNotIn("\n", fusion["commit_title"])
                self.assertTrue(fusion["commit_title"].endswith("(#60)"))
                self.assertIsNone(publicar.fila_de_la_linea(fusion["commit_title"] + "\n\n" + fusion["commit_message"]))

    def test_solo_las_de_programa_llevan_la_linea(self):
        fusion = permisos.datos_de_fusion("c" * 40, 61, "Ficha", sol(), "eva", 7)
        self.assertEqual({"canal": "rance_es", "cuenta": "eva", "cuentaId": 7, "tipo": "central", "juego": "rance-x",
                          "directa": True, "propuesta": 61}, publicar.fila_de_la_linea(fusion["commit_message"]))
        otra = permisos.datos_de_fusion("c" * 40, 62, "Parche", solicitudes.Solicitud("canal", "rance_es", None, False),
                                        "eva", 7)
        self.assertIsNone(publicar.fila_de_la_linea(otra["commit_message"]))


class NadieMasLoEscribe(unittest.TestCase):
    def test_un_canal_no_toca_el_historial(self):
        p = Propuesta(main_es(verificado=True)).poner("historial/central/2026-11.json",
                                                      {"esquema": 1, "mes": "2026-11", "filas": []})
        # Ni un Administrador de un canal verificado ni uno del canal oficial: es del Dueño (y del robot).
        self.assertTrue(juzgar(p, admin()))
        oficial = Permisos(Rol.ADMINISTRADOR, por_canal={"ornizen": Rol.ADMINISTRADOR}, cuenta_id=YO)
        motivos = juzgar(p, oficial)
        self.assertTrue(any("historial/central/2026-11.json" in m for m in motivos), motivos)


class ApiConPropuestas(ApiFalsa):
    """Además, `GET /pulls/<n>`: lo que GitHub sabe de cada propuesta (o un fallo de red si `caida`)."""

    def __init__(self, remoto, propuestas, caida=False):
        super().__init__(remoto)
        self.de_github, self.caida = propuestas, caida

    def __call__(self, metodo, ruta, datos=None, tolerar=()):
        if metodo == "GET" and re.fullmatch(r"/pulls/\d+", ruta):
            self.llamadas.append((metodo, ruta, datos))
            if self.caida:
                raise RuntimeError(f"GitHub respondió 502 a GET {ruta}")
            propuesta = self.de_github.get(int(ruta.rsplit("/", 1)[1]))
            if propuesta is None and 404 not in tolerar:
                raise RuntimeError(f"GitHub respondió 404 a GET {ruta}")
            return propuesta
        return super().__call__(metodo, ruta, datos, tolerar)


class EnElTrabajo(unittest.TestCase):
    # Lo de TrabajoEntero sin heredar sus pruebas (si no, se correrían otra vez aquí).
    tearDown, del_remoto = TrabajoEntero.tearDown, TrabajoEntero.del_remoto

    def setUp(self):
        TrabajoEntero.setUp(self)
        self.de_github, self.caida = {}, False

    def correr(self):
        if not self.local.exists():
            g("init", "-q", str(self.local), cwd=self.tmp.name)
        os.chdir(self.local)
        api, avisos = ApiConPropuestas(self.remoto, self.de_github, self.caida), []
        base = publicar.regenerar_catalogo(api, self.remoto, dict(os.environ), avisos.append)
        escrito = publicar.escribir_publicado(self.remoto, dict(os.environ), base, avisos.append)
        os.chdir(self.antes)
        return api, avisos, escrito

    def preguntas(self, api):
        return [c for c in api.llamadas if c[0] == "GET" and re.fullmatch(r"/pulls/\d+", c[1])]

    def subir_main(self, archivos, mensaje="cambio", vacio=False, confirmar=True):
        """Sube un commit a `main`. Con `confirmar`, GitHub dice que su propuesta se fusionó ahí y es de esa cuenta."""
        sha = self._subir(archivos, mensaje, vacio)
        fila = publicar.fila_de_la_linea(mensaje)
        if confirmar and fila:
            self.de_github[fila["propuesta"]] = {"merged": True, "merge_commit_sha": sha,
                                                 "user": {"login": fila["cuenta"], "id": fila["cuentaId"]}}
        return sha

    def _subir(self, archivos, mensaje, vacio):
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
        g("commit", "-q", *(["--allow-empty"] if vacio else []), "-m", mensaje, cwd=trabajo)
        g("push", "-q", "origin", "HEAD:main", cwd=trabajo)
        return g("rev-parse", "HEAD", cwd=trabajo)

    def preparar(self):
        catalogo = todo_el_modelo()
        archivos = sueltos_de(catalogo)
        canales_main = publicar._json({"esquema": 1, "versionCatalogo": catalogo["versionCatalogo"],
                                       "canales": publicar.canales_para_main(archivos)})
        self.subir_main({**archivos, "catalogo/catalogo.json": particion.texto_json(catalogo),
                         publicar.RUTA_CANALES_MAIN: canales_main})
        self.correr()
        return archivos

    def meses(self):
        salida = subprocess.run(["git", "--git-dir", self.remoto, "ls-tree", "-r", "--name-only", "main", "--",
                                 "historial/central/"], capture_output=True, check=True).stdout.decode().split()
        return {r: json.loads(self.del_remoto("main", r)) for r in salida}

    def test_un_cambio_en_la_ficha_deja_su_fila_con_el_catalogo(self):
        archivos = self.preparar()
        self.assertEqual({}, self.meses())
        juego = json.loads(archivos["juegos/rance-x/juego.json"])
        juego["titulo"] = "Rance X (nuevo)"
        juego["sinopsis"] = "Otra"
        sha = self.subir_main({"juegos/rance-x/juego.json": particion.texto_json(juego)},
                              f"Ficha (#42)\n\n{solicitudes.linea_historial(sol(), 'eva', 7, 42)}")
        api, avisos, _ = self.correr()
        meses = self.meses()
        self.assertEqual(1, len(meses))
        ruta, datos = next(iter(meses.items()))
        self.assertRegex(ruta, r"^historial/central/\d{4}-\d{2}\.json$")
        self.assertEqual((1, ruta[-12:-5]), (datos["esquema"], datos["mes"]))
        fila = datos["filas"][0]
        self.assertEqual({"canal": "rance_es", "cuenta": "eva", "cuentaId": 7, "tipo": "central", "juego": "rance-x",
                          "directa": True, "propuesta": 42, "commit": sha},
                         {k: v for k, v in fila.items() if k not in ("fecha", "cambios")})
        self.assertEqual({"juego.json": ["sinopsis", "titulo"]}, fila["cambios"])
        self.assertRegex(fila["fecha"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        # En la misma propuesta que el catálogo (una sola fusión), y el catálogo sube de versión.
        self.assertEqual(1, len([c for c in api.llamadas if c[0] == "PUT"]))
        self.assertEqual(32, json.loads(self.del_remoto("main", "catalogo/catalogo.json"))["versionCatalogo"])
        # Otra pasada: nada nuevo (la fila ya está en `main` y no se recalcula).
        api, avisos, _ = self.correr()
        self.assertFalse([c for c in api.llamadas if c[0] in ("PUT", "POST")])

    def test_solo_historial_no_sube_la_version_del_catalogo(self):
        self.preparar()
        self.subir_main({}, f"Algo (#7)\n\n{solicitudes.linea_historial(sol(tipo='edicion', directa=False), 'eva', 7, 7)}",
                        vacio=True)
        api, avisos, _ = self.correr()
        self.assertEqual(31, json.loads(self.del_remoto("main", "catalogo/catalogo.json"))["versionCatalogo"])
        propuesta = next(c for c in api.llamadas if c[:2] == ("POST", "/pulls"))[2]
        self.assertEqual("Historial global del programa", propuesta["title"])
        fila = next(iter(self.meses().values()))["filas"][0]
        self.assertEqual(({}, False, "edicion"), (fila["cambios"], fila["directa"], fila["tipo"]))

    def test_una_linea_rota_no_frena_nada_y_se_avisa(self):
        self.preparar()
        self.subir_main({}, solicitudes.MARCA_HISTORIAL + '{"v": 1, "canal": "../x"}', vacio=True)
        api, avisos, _ = self.correr()
        self.assertEqual({}, self.meses())
        self.assertTrue(any("no se entiende" in a for a in avisos))
        self.assertFalse([c for c in api.llamadas if c[0] == "PUT"])

    def test_edicion_nueva_e_imagen(self):
        archivos = self.preparar()
        juego = json.loads(archivos["juegos/rance-x/juego.json"])
        nuevos = {"juegos/rance-x/imagenes/portada-2.png": b"\x89PNG",
                  "juegos/rance-x/ediciones/zz-nueva.json": particion.texto_json({"esquema": 1, "id": "zz-nueva"})}
        self.subir_main({**nuevos, "juegos/rance-x/juego.json": particion.texto_json(juego)},
                        solicitudes.linea_historial(sol(tipo="edicion"), "eva", 7, 9))
        self.correr()
        fila = next(iter(self.meses().values()))["filas"][0]
        self.assertEqual({"ediciones/zz-nueva.json": "nuevo", "imagenes/portada-2.png": "cambiado"}, fila["cambios"])

    def test_un_mes_que_no_cabe_se_queda_con_lo_nuevo(self):
        self.preparar()
        for n in range(1, 6):
            self.subir_main({}, solicitudes.linea_historial(sol(tipo="edicion"), "eva", 7, n), vacio=True)
        with mock.patch.object(publicar, "TOPE_HISTORIAL", 900):
            api, avisos, _ = self.correr()
        datos = next(iter(self.meses().values()))
        self.assertLessEqual(len(publicar._json(datos)), 900)
        self.assertGreater(datos["recortadas"], 0)
        self.assertEqual(5, datos["recortadas"] + len(datos["filas"]))
        self.assertEqual(5, datos["filas"][-1]["propuesta"])  # se quedan las más nuevas
        self.assertTrue(any("recortadas" in a for a in avisos))

    def test_un_historial_ilegible_en_main_se_rehace(self):
        self.preparar()
        sha = self.subir_main({}, solicitudes.linea_historial(sol(tipo="edicion"), "eva", 7, 3), vacio=True)
        self.correr()
        ruta = next(iter(self.meses()))
        self.subir_main({ruta: b"{roto"})
        self.correr()
        self.assertEqual([sha], [f["commit"] for f in self.meses()[ruta]["filas"]])


    def test_falsa_en_rama_ajena(self):
        # Un miembro escribe la línea en un commit de su parche (o el Dueño fusiona a mano una propuesta así): GitHub
        # no confirma la propuesta, la cuenta o el commit, y no sale nada.
        self.preparar()
        linea = solicitudes.linea_historial(sol(tipo="edicion", canal="ornizen"), "0rnizL", 1, 60)
        self.subir_main({}, f"Parche (#60)\n\n* traducción\n\n{linea}", vacio=True, confirmar=False)
        self.de_github[60] = {"merged": True, "merge_commit_sha": "f" * 40, "user": {"login": "eva", "id": 7}}
        otra = self.subir_main({}, solicitudes.linea_historial(sol(tipo="edicion"), "eva", 7, 61), vacio=True,
                               confirmar=False)
        self.de_github[61] = {"merged": True, "merge_commit_sha": otra, "user": {"login": "eva", "id": 8}}
        sin_fusionar = self.subir_main({}, solicitudes.linea_historial(sol(tipo="edicion"), "eva", 7, 62), vacio=True,
                                       confirmar=False)
        self.de_github[62] = {"merged": False, "merge_commit_sha": sin_fusionar, "user": {"login": "eva", "id": 7}}
        self.subir_main({}, solicitudes.linea_historial(sol(tipo="edicion"), "eva", 7, 63), vacio=True,
                        confirmar=False)  # #63 no existe (404)
        api, avisos, _ = self.correr()
        self.assertEqual({}, self.meses())
        self.assertEqual(4, len([a for a in avisos if "no lo confirma" in a]), avisos)
        self.assertFalse([c for c in api.llamadas if c[0] == "PUT"])

    def test_un_cambio_central_que_no_cambia_nada_no_sale(self):
        self.preparar()
        self.subir_main({}, solicitudes.linea_historial(sol(), "eva", 7, 5), vacio=True)
        api, avisos, _ = self.correr()
        self.assertEqual({}, self.meses())
        self.assertEqual([], self.preguntas(api))

    def test_el_mes_lleno_no_se_recorta_otra_vez_en_cada_pasada(self):
        self.preparar()
        for n in range(1, 6):
            self.subir_main({}, solicitudes.linea_historial(sol(tipo="edicion"), "eva", 7, n), vacio=True)
        with mock.patch.object(publicar, "TOPE_HISTORIAL", 900):
            self.correr()
            primera = self.meses()
            for _ in range(2):  # segunda y tercera pasada: nada cambia, ni propuestas ni preguntas a GitHub
                api, avisos, _ = self.correr()
                self.assertEqual(primera, self.meses())
                self.assertFalse([c for c in api.llamadas if c[0] in ("PUT", "POST")])
                self.assertEqual([], self.preguntas(api))
                self.assertFalse([a for a in avisos if "recortadas" in a])
            self.subir_main({}, solicitudes.linea_historial(sol(tipo="edicion"), "eva", 7, 6), vacio=True)
            self.correr()
            datos = next(iter(self.meses().values()))
            self.assertEqual(6, datos["recortadas"] + len(datos["filas"]))
            self.assertEqual(6, datos["filas"][-1]["propuesta"])
            self.assertEqual([], self.preguntas(self.correr()[0]))  # otra pasada: no pregunta nada

    def test_sin_respuesta_de_github_se_espera_a_la_siguiente(self):
        self.preparar()
        for n in (1, 2):
            self.subir_main({}, solicitudes.linea_historial(sol(tipo="edicion"), "eva", 7, n), vacio=True)
        self.caida = True
        api, avisos, _ = self.correr()
        self.assertEqual({}, self.meses())
        self.assertEqual(1, len(self.preguntas(api)))  # se para en la primera, no salta a la segunda
        self.assertTrue(any("No se ha podido preguntar" in a for a in avisos))
        self.caida = False
        self.correr()
        self.assertEqual([1, 2], [f["propuesta"] for f in next(iter(self.meses().values()))["filas"]])

    def test_tope_de_preguntas_por_pasada(self):
        self.preparar()
        for n in range(1, 5):
            self.subir_main({}, solicitudes.linea_historial(sol(tipo="edicion"), "eva", 7, n), vacio=True)
        with mock.patch.object(publicar, "TOPE_COMPROBACIONES", 3):
            api, avisos, _ = self.correr()
            self.assertEqual(3, len(self.preguntas(api)))
            self.assertEqual([1, 2, 3], [f["propuesta"] for f in next(iter(self.meses().values()))["filas"]])
            api, _, _ = self.correr()
            self.assertEqual(1, len(self.preguntas(api)))
        self.assertEqual([1, 2, 3, 4], [f["propuesta"] for f in next(iter(self.meses().values()))["filas"]])

    def test_mismo_segundo_en_el_orden_de_main(self):
        self.preparar()
        entorno = dict(os.environ, GIT_COMMITTER_DATE="2026-11-21T10:00:00Z", GIT_AUTHOR_DATE="2026-11-21T10:00:00Z")
        with mock.patch.dict(os.environ, entorno):
            for n in range(1, 8):
                self.subir_main({}, solicitudes.linea_historial(sol(tipo="edicion"), "eva", 7, n), vacio=True)
        self.correr()
        filas = next(iter(self.meses().values()))["filas"]
        self.assertEqual(list(range(1, 8)), [f["propuesta"] for f in filas])
        self.assertEqual({"2026-11-21T10:00:00Z"}, {f["fecha"] for f in filas})


if __name__ == "__main__":
    unittest.main()
